from app.services.entity_resolution import (
    ConceptRegistry,
    acronym_of,
    find_acronym_definitions,
    fuzzy_same,
    normalize,
)
from app.services.graph_extraction_service import heading_to_concept


def test_normalize_and_plurals():
    assert normalize("Convolutional Neural Networks") == normalize("convolutional neural network")
    assert normalize("  Gradient-Descent ") == normalize("gradient descent")


def test_acronyms():
    assert acronym_of("Stochastic Gradient Descent") == "SGD"
    assert ("Gradient Descent", "GD") in find_acronym_definitions("We use Gradient Descent (GD) here.")


def test_fuzzy_matching_handles_typos_but_not_different_concepts():
    assert fuzzy_same("gradient decent", "gradient descent")
    assert not fuzzy_same("logistic regression", "linear regression")


def test_registry_resolves_aliases_to_one_concept():
    reg = ConceptRegistry(seed_aliases={"GD": "gradient descent"})
    key = reg.add("Gradient Descent (GD)")
    assert reg.resolve("gradient descent") == key
    assert reg.resolve("GD") == key
    assert reg.resolve("Gradient decent") == key
    assert reg.resolve("Logistic Regression") is None


def test_generic_headings_are_not_concepts():
    for h in ("Agenda", "Summary", "Questions?", "Acknowledgment"):
        assert heading_to_concept(h) is None
    assert heading_to_concept("What is a Decision Tree?") == "Decision Tree"
