"""Fixture for the self-heal loop's no-model test rounds.

The improver workflow's modify round appends one test to this file and its
delete round removes it, each inside a throwaway pull request that is closed
and never merged. The file therefore has to exist on main. It holds one real
test so that it is an ordinary member of the tests class.
See .github/workflows/vault-self-heal.yml, input no_model_kind.
"""


def test_the_fixture_is_collected_and_passes():
    assert sorted([3, 1, 2]) == [1, 2, 3]
