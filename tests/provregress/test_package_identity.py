def test_new_package_exposes_expected_version() -> None:
    import provregress

    assert provregress.__version__ == "0.3.0"


def test_legacy_package_remains_importable() -> None:
    import llmtestlab

    assert llmtestlab is not None
