# Contributing to Fantasy Football MCP

Thank you for your interest in contributing to Fantasy Football MCP! This document provides guidelines and instructions for contributing.

## Code of Conduct

Please be respectful and professional in all interactions. We aim to create a welcoming environment for all contributors.

## How to Contribute

### Reporting Issues

1. Check if the issue already exists
2. Create a new issue with:
   - Clear title and description
   - Steps to reproduce (if applicable)
   - Expected vs actual behavior
   - Environment details (OS, Python version, etc.)

### Submitting Pull Requests

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Make your changes
4. Run tests (`pytest tests/`)
5. Commit your changes (`git commit -m 'Add amazing feature'`)
6. Push to your branch (`git push origin feature/amazing-feature`)
7. Open a Pull Request

### Development Setup

1. Clone your fork:
```bash
git clone https://github.com/yourusername/fantasy-football-mcp.git
cd fantasy-football-mcp
```

2. Create virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Copy `.env.example` to `.env` and configure with your Yahoo API credentials

5. Run tests:
```bash
pytest tests/
```

## Coding Standards

- Follow PEP 8 style guidelines
- Use type hints where appropriate
- Write docstrings for functions and classes
- Keep functions focused and small
- Add tests for new features

### Code Formatting

We use Black for code formatting:
```bash
black . --line-length 100
```

### Testing

- Write tests for new features
- Maintain or improve code coverage
- Test edge cases and error conditions
- Use meaningful test names

## API Credentials

**IMPORTANT**: Never commit API credentials or tokens!

- Use `.env` files for local development
- Ensure `.env` is in `.gitignore`
- Use placeholders in example files
- Document required credentials in README

## Feature Requests

We welcome feature suggestions! Please:

1. Check existing issues/PRs first
2. Open an issue describing:
   - The problem it solves
   - Proposed implementation
   - Any alternatives considered

## Documentation

- Update README.md for user-facing changes
- Update CLAUDE.md for AI assistant context
- Include docstrings in code
- Add inline comments for complex logic

## Security

- Never expose API keys or secrets
- Report security vulnerabilities privately
- Follow secure coding practices
- Validate and sanitize inputs

## Questions?

Feel free to open an issue for questions about contributing.

Thank you for helping improve Fantasy Football MCP!