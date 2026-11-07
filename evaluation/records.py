"""Asset-level metric aggregation, explicitly retaining missing and failed denominators."""
from collections import defaultdict
import math
import statistics


def summarize(records, totals, shape_comparison=None):
    groups=defaultdict(list)
    for record in records:
        key=tuple(record[k] for k in ('method','config_id','seed','protocol_id','metric'))
        groups[key].append(record)
    success={key:{x['sample_id'] for x in values if x['status']=='complete' and x['value'] is not None and math.isfinite(x['value'])}
             for key,values in groups.items()}
    result=[]
    for key, values in sorted(groups.items()):
        method,config,seed,protocol,metric=key
        numbers=[x['value'] for x in values if x['sample_id'] in success[key]]
        total=totals[(method,config,seed)]
        failed=sum(x['status']=='failed' for x in values)
        eligible=['wt','trellis2','wt_trellis2'] if protocol=='gso-shape-sim3-v1' else ['wt','wt_trellis2']
        common_mean=common_count=None
        pairs = (shape_comparison if protocol=='gso-shape-sim3-v1' and shape_comparison is not None
                 else [(m, 'defaults-v1') for m in eligible])
        if (method, config) in pairs:
            sets=[success.get((m,c,seed,protocol,metric),set()) for m,c in pairs]
            common=set.intersection(*sets)
            common_numbers=[x['value'] for x in values if x['sample_id'] in common]
            common_count=len(common_numbers)
            common_mean=statistics.mean(common_numbers) if common_numbers else None
        result.append(dict(method=method,config_id=config,seed=seed,protocol_id=protocol,metric=metric,
            mean=statistics.mean(numbers) if numbers else None,
            std=statistics.pstdev(numbers) if numbers else None,successful=len(numbers),total=total,
            failed=failed,pending=total-len(values),not_applicable=sum(x['status']=='N/A' for x in values),
            failure_rate=failed/total if total else None,common_mean=common_mean,common_count=common_count))
    return result
