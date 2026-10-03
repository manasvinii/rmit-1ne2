import pytest

from app.services.query_router import Intent, Route, route_query


@pytest.mark.parametrize("query,route,intent", [
    ("When is Assignment 2 due?", Route.STRUCTURED_CANVAS, Intent.DEADLINE),
    ("What are my courses?", Route.STRUCTURED_CANVAS, Intent.COURSE_LIST),
    ("What does the slide say about ReLU?", Route.VECTOR_RAG, Intent.LECTURE_FACT),
    ("Show where my lecturer discussed backpropagation", Route.VECTOR_RAG, Intent.LOCATE),
    ("What are the prerequisites for CNNs?", Route.GRAPH, Intent.PREREQUISITES),
    ("What should I revise before CNNs?", Route.GRAPH_VECTOR, Intent.PREREQUISITES),
    ("Where was gradient descent first introduced?", Route.GRAPH, Intent.CONCEPT_TIMELINE),
    ("How does lecture 3 connect to lecture 7?", Route.GRAPH_VECTOR, Intent.LECTURE_CONNECTION),
    ("Which lectures are relevant to Assignment 2?", Route.GRAPH_VECTOR, Intent.ASSIGNMENT_REVISION),
])
def test_routes(query, route, intent):
    r = route_query(query)
    assert (r.route, r.intent) == (route, intent)


def test_week_extraction():
    assert route_query("How does Lecture 3 relate to week 7?").weeks == [3, 7]
