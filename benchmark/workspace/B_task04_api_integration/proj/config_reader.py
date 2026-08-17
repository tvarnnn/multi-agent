def get_setting(config: dict, key: str) -> str:
    if key in config:
        return config[key]
    else:
        raise KeyError(f'Key \\