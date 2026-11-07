"""Bound inference-only LayerNorm32 temporaries without splitting feature reductions."""
from contextlib import contextmanager
import json
from pathlib import Path

import torch


@contextmanager
def bounded_layernorm(module, max_elements=16_777_216):
    from trellis2.modules.norm import LayerNorm32
    if max_elements < 1:
        raise ValueError('max_elements must be positive')
    stats = dict(max_elements=max_elements, patched_layers=0, tiled_calls=0, max_input_elements=0)
    originals = []
    try:
        for child in module.modules():
            # ChannelLayerNorm32 has a separate permutation contract; leave it alone.
            if type(child) is not LayerNorm32:
                continue
            original = child.forward
            existed, value = 'forward' in child.__dict__, child.__dict__.get('forward')
            normalized_shape = tuple(child.normalized_shape)

            def forward(x, original=original, normalized_shape=normalized_shape):
                if (torch.is_grad_enabled() or x.ndim != 2
                        or normalized_shape != (x.shape[1],) or x.numel() <= max_elements):
                    return original(x)
                stats['tiled_calls'] += 1
                stats['max_input_elements'] = max(stats['max_input_elements'], x.numel())
                rows = max(1, max_elements // x.shape[1])
                output = torch.empty(x.shape, device=x.device, dtype=x.dtype)
                for start in range(0, x.shape[0], rows):
                    output[start:start + rows].copy_(original(x[start:start + rows]))
                return output

            child.forward = forward
            originals.append((child, existed, value))
        stats['patched_layers'] = len(originals)
        yield stats
    finally:
        for child, existed, value in reversed(originals):
            if existed:
                child.forward = value
            else:
                del child.forward


def check(destination):
    from trellis2.modules.norm import LayerNorm32
    torch.manual_seed(42)
    cases = []
    with torch.no_grad():
        for dtype in (torch.float16, torch.bfloat16, torch.float32):
            for channels in (16, 32, 64, 128, 256, 1024):
                for strided in (False, True):
                    norm = LayerNorm32(channels).cuda()
                    norm.weight.uniform_(.5, 1.5)
                    norm.bias.uniform_(-.2, .2)
                    x = torch.randn(2053, channels * (2 if strided else 1), device='cuda', dtype=dtype)
                    if strided:
                        x = x[:, ::2]
                    x[0].fill_(1)
                    expected = norm(x)
                    with bounded_layernorm(norm, max_elements=4096) as stats:
                        actual = norm(x)
                    assert 'forward' not in norm.__dict__
                    assert stats['tiled_calls'] == 1
                    assert torch.equal(actual, expected), (dtype, channels, strided, (actual-expected).abs().max().item())
                    cases.append(dict(dtype=str(dtype), channels=channels, strided=strided, bitwise_equal=True))
        norm = LayerNorm32(64).cuda()
        x = torch.randn(1_048_576, 64, device='cuda', dtype=torch.float16)
        torch.cuda.synchronize()
        torch.cuda.reset_peak_memory_stats()
        before = torch.cuda.memory_allocated()
        expected = norm(x)
        torch.cuda.synchronize()
        native_extra = torch.cuda.max_memory_allocated() - before
        torch.cuda.reset_peak_memory_stats()
        before = torch.cuda.memory_allocated()
        with bounded_layernorm(norm) as stats:
            actual = norm(x)
        torch.cuda.synchronize()
        bounded_extra = torch.cuda.max_memory_allocated() - before
        assert torch.equal(actual, expected)
        assert bounded_extra < native_extra * .65, (native_extra, bounded_extra)
    # Training/autograd remains delegated to the original operation.
    norm = LayerNorm32(32).cuda()
    x = torch.randn(128, 32, device='cuda', requires_grad=True)
    with bounded_layernorm(norm, max_elements=64) as stats:
        norm(x).square().mean().backward()
    assert stats['tiled_calls'] == 0 and x.grad is not None and torch.isfinite(x.grad).all()
    result = dict(status='passed', torch=torch.__version__, cuda=torch.version.cuda,
                  gpu=torch.cuda.get_device_name(), seed=42, cases=cases,
                  large_case_bitwise_equal=True, original_extra_bytes=native_extra,
                  bounded_extra_bytes=bounded_extra, autograd_fallback=True,
                  policy='Original LayerNorm32 per independent row; unchanged feature-axis reduction, dtype, weights and epsilon')
    Path(destination).write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--check', required=True)
    check(parser.parse_args().check)
