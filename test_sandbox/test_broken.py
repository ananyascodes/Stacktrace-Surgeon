# test_sandbox/test_broken.py
def test_addition():
    assert 1 + 1 == 2

def test_runtime_crash():
    my_dict = {"name": "Surgeon"}
    # This will throw a KeyError because "age" doesn't exist
    print(my_dict["age"])