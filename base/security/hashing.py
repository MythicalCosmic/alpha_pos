from django.contrib.auth.hashers import make_password, check_password


def hash_password(password):
    return make_password(password)


def verify_password(password, hashed):
    return check_password(password, hashed)
