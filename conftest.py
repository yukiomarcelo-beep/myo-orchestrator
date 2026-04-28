def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "pre_removal: testes que so passam apos execucao da LESSON-013 (git rm dos legados)",
    )
