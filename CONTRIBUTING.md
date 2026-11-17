# Contributing to gharc

Thank you for your interest in `gharc`! We welcome contributions from the community to help make GitHub Archive data accessible to everyone.

## Getting Help

If you have a question about using `gharc`, run into unexpected behavior, or want to discuss an idea before opening a pull request, please open an issue on the [GitHub issue tracker](https://github.com/aravpanwar/gharc/issues). For bug reports, include the command you ran, what you expected, and what happened (the `--debug` flag prints a full traceback that is helpful to attach).

## How to Report Bugs
Please open an issue on GitHub if you encounter:
- Downloads failing consistently.
- Parsing errors with specific event types.
- Feature requests for new filters.

## How to Submit Changes
1. Fork the repository.
2. Create a branch named for the change (`git checkout -b resume-on-parquet`).
3. Make your changes, adding a test for any behavior you fix or add.
4. **Run the tests**: Ensure `pytest` passes locally.
5. Commit with a message that says what the change is for, then push the branch.
6. Open a Pull Request describing the problem and how you checked the fix.

## Development Setup
```bash
# Clone and install dependencies
git clone https://github.com/aravpanwar/gharc.git
cd gharc
python3 -m venv venv
source venv/bin/activate        # Windows PowerShell: .\venv\Scripts\Activate.ps1
pip install -e ".[test,fast]"   # fast adds orjson so both JSON parsers are tested
```

## Running Tests
```bash
pytest tests/
```
