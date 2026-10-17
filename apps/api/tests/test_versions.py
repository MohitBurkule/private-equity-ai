from app.versions import split_version, superseded


def test_version_token_splits_off_the_lineage_name():
    assert split_version("Acme_model_v3.xlsx") == ("acme_model", (3,))
    assert split_version("Acme Model v5.2.xlsx") == ("acme model", (5, 2))
    assert split_version("Acme_CIM.pdf") == ("acme_cim", None)


def test_newest_version_supersedes_older_only_within_a_lineage():
    names = {1: "Acme_model_v3.xlsx", 2: "Acme_model_v5.xlsx", 3: "Acme_CIM.pdf", 4: "Beta_model_v1.xlsx"}
    assert superseded(names) == {1: 2}
