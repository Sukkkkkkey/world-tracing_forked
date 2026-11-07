import pytest

from wt.experiment import identifier


def test_original_unicode_asset_id_is_preserved():
    asset = 'Pokémon_Omega_Ruby_Alpha_Sapphire_Dual_Pack_Nintendo_3DS'
    assert identifier(asset) == asset


@pytest.mark.parametrize('value', ['', '.', '..', '../asset', 'a/b', 'a\\b', '/tmp/asset', 'a\n', 'a b', None])
def test_directory_ids_reject_path_components_and_control_characters(value):
    with pytest.raises(ValueError, match='Invalid directory ID'):
        identifier(value)
