from qdrant_loader.config.graph import GraphConfig


def test_store_kwargs_defaults_password_to_none():
    config = GraphConfig()

    kwargs = config.store_kwargs()

    assert kwargs == {
        "host": "localhost",
        "port": 6379,
        "password": None,
        "graph_name": "default_graph",
        "max_connections": 10,
    }


def test_store_kwargs_unwraps_configured_password():
    config = GraphConfig(
        connection={
            "host": "falkordb.internal",
            "port": 6380,
            "password": "s3cret",
        },
        graph_name="my_graph",
        pool={"max_connections": 20},
    )

    kwargs = config.store_kwargs()

    assert kwargs["password"] == "s3cret"
    assert kwargs == {
        "host": "falkordb.internal",
        "port": 6380,
        "password": "s3cret",
        "graph_name": "my_graph",
        "max_connections": 20,
    }
