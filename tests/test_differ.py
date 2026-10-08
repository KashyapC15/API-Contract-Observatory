from api.differ import compare_specs


def test_detects_component_field_add_remove_and_type_change() -> None:
    old = {
        "paths": {},
        "components": {
            "schemas": {
                "User": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "age": {"type": "integer"},
                    },
                }
            }
        },
    }
    new = {
        "paths": {},
        "components": {
            "schemas": {
                "User": {
                    "type": "object",
                    "properties": {
                        "fullName": {"type": "string"},
                        "age": {"type": "number"},
                    },
                }
            }
        },
    }

    assert [
        change.model_dump() for change in compare_specs(old, new)
    ] == [
        {"type": "FIELD_ADDED", "location": "User.fullName"},
        {"type": "FIELD_REMOVED", "location": "User.name"},
        {"type": "FIELD_TYPE_CHANGED", "location": "User.age"},
    ]


def test_detects_endpoints_and_newly_required_fields() -> None:
    old = {
        "paths": {"/old": {"get": {}}},
        "components": {"schemas": {"User": {"properties": {"email": {"type": "string"}}}}},
    }
    new = {
        "paths": {"/new": {"post": {}}},
        "components": {
            "schemas": {
                "User": {
                    "properties": {"email": {"type": "string"}},
                    "required": ["email"],
                }
            }
        },
    }

    assert [
        change.model_dump() for change in compare_specs(old, new)
    ] == [
        {"type": "ENDPOINT_ADDED", "location": "POST /new"},
        {"type": "ENDPOINT_REMOVED", "location": "GET /old"},
        {"type": "REQUIRED_FIELD_ADDED", "location": "User.email"},
    ]


def test_detects_inline_response_property_removal() -> None:
    old = {
        "paths": {
            "/users": {
                "get": {
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "name": {"type": "string"}
                                        },
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
    new = {
        "paths": {
            "/users": {
                "get": {
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {},
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    changes = compare_specs(old, new)

    assert [change.model_dump() for change in changes] == [
        {
            "type": "RESPONSE_PROPERTY_REMOVED",
            "location": "GET /users.responses.200.name",
        }
    ]
