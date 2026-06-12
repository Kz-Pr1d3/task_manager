from src.core.security import hash_password, verify_password


def test__hash_password__is_hashed():
    password = "test"
    hashed_pass = hash_password(password=password)
    assert hashed_pass != password
    assert hashed_pass.startswith("$argon2")


def test__hash_password__salting_success():
    password = "test"
    hashed_pass_1 = hash_password(password=password)
    hashed_pass_2 = hash_password(password=password)

    assert hashed_pass_1 != hashed_pass_2


def test__verify_password__success():
    password = "test"
    hashed_pass = hash_password(password=password)

    is_correct = verify_password(plain=password, hashed=hashed_pass)
    assert is_correct
