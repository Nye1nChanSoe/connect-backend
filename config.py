from datetime import timedelta


class Config:
    JWT_SECRET = 'secret_key'
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(seconds=20)