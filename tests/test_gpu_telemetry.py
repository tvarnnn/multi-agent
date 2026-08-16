from agent_platform.orchestrator.gpu_telemetry import query_gpu_memory


def test_parses_valid_nvidia_smi_csv_output():
    def fake_run(*args, **kwargs):
        class Result:
            returncode = 0
            stdout = "1215, 12227\n"
        return Result()

    result = query_gpu_memory(nvidia_smi=fake_run)
    assert result == {"used_mib": 1215, "total_mib": 12227}


def test_returns_none_when_nvidia_smi_is_unavailable():
    def fake_run(*args, **kwargs):
        raise FileNotFoundError("nvidia-smi not found")

    assert query_gpu_memory(nvidia_smi=fake_run) is None


def test_returns_none_on_nonzero_exit_code():
    def fake_run(*args, **kwargs):
        class Result:
            returncode = 1
            stdout = ""
        return Result()

    assert query_gpu_memory(nvidia_smi=fake_run) is None


def test_returns_none_on_malformed_output():
    def fake_run(*args, **kwargs):
        class Result:
            returncode = 0
            stdout = "not,numbers\n"
        return Result()

    assert query_gpu_memory(nvidia_smi=fake_run) is None
