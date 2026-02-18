def retry(*args, **kwargs):
    def deco(fn):
        return fn
    return deco


def retry_if_exception_type(*args, **kwargs):
    return None


def stop_after_attempt(*args, **kwargs):
    return None


def wait_exponential(*args, **kwargs):
    return None
