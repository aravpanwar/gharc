# Contributing to gharc

Thank you for your interest in `gharc`! We welcome contributions from the community to help make GitHub Archive data accessible to everyone.

## How to Report Bugs
Please open an issue on GitHub if you encounter:
- Downloads failing consistently.
- Parsing errors with specific event types.
- Feature requests for new filters.

## How to Submit Changes
1. Fork the repository.
2. Create a new branch (`git checkout -b feature/amazing-feature`).
3. Make your changes.
4. **Run the tests**: Ensure `pytest` passes locally.
5. Commit your changes (`git commit -m 'Add some amazing feature'`).
6. Push to the branch (`git push origin feature/amazing-feature`).
7. Open a Pull Request.

## Development Setup
```bash
# Clone and install dependencies
git clone [https://github.com/YOUR_USERNAME/gharc.git](https://github.com/YOUR_USERNAME/gharc.git)
cd gharc
python3 -m venv venv
source venv/bin/activate
pip install -e .
pip install pytest mock
