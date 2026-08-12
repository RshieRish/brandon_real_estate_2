from services.command_file_storage import command_object_key


def test_command_object_key_uses_private_prefix_and_safe_filename():
    key = command_object_key("Agreement Final (1).pdf")
    assert key.startswith("command-files/")
    assert key.endswith("-Agreement-Final-1.pdf")
    assert " " not in key
