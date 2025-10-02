# Fantasy Football MCP Server - Test Suite

Comprehensive pytest test suite for ensuring code quality and reliability.

## Test Structure

```
tests/
├── conftest.py              # Shared fixtures and test configuration
├── unit/                    # Unit tests for individual modules
│   ├── test_api_client.py       # Yahoo API client tests
│   ├── test_handlers.py         # MCP tool handler tests
│   ├── test_lineup_optimizer.py # Lineup optimization logic tests
│   └── test_parsers.py          # Yahoo API response parser tests
└── integration/             # Integration tests for complete flows
    └── test_mcp_tools.py        # End-to-end MCP tool flow tests
```

## Running Tests

### Run All Tests
```bash
pytest tests/ -v
```

### Run Unit Tests Only
```bash
pytest tests/unit/ -v
```

### Run Integration Tests Only
```bash
pytest tests/integration/ -v
```

### Run with Coverage Report
```bash
pytest tests/ --cov=src --cov=lineup_optimizer --cov-report=term-missing --cov-report=html
```

### Run Specific Test File
```bash
pytest tests/unit/test_api_client.py -v
```

### Run Tests Matching Pattern
```bash
pytest tests/ -k "test_yahoo" -v
```

## Test Results Summary

**Total Tests**: 70 tests (62 unit + 8 integration)  
**Pass Rate**: 100% ✅

### Coverage by Module

| Module | Statements | Coverage | Notes |
|--------|-----------|----------|-------|
| **src/api/yahoo_client.py** | 64 | **97%** | API client, token refresh, rate limiting |
| **src/handlers/admin_handlers.py** | 12 | **100%** | Admin MCP tool handlers |
| **src/handlers/league_handlers.py** | 64 | **86%** | League MCP tool handlers |
| **src/parsers/yahoo_parsers.py** | 125 | **86%** | Yahoo API response parsing |
| **lineup_optimizer.py** | 312 | **51%** | Core optimization logic |

### Test Categories

#### Unit Tests (62 tests)

**API Client Tests** (`test_api_client.py`) - 12 tests
- ✅ Token management (get/set access tokens)
- ✅ Yahoo API calls with caching
- ✅ Rate limiting integration
- ✅ Automatic token refresh on 401 errors
- ✅ Error handling for API failures
- ✅ Cache hit/miss behavior

**Handler Tests** (`test_handlers.py`) - 9 tests
- ✅ Admin handlers (token refresh, API status, cache management)
- ✅ League handlers (get leagues, standings, teams)
- ✅ Error handling for missing parameters
- ✅ Response formatting

**Lineup Optimizer Tests** (`test_lineup_optimizer.py`) - 29 tests
- ✅ Utility functions (coerce_float, coerce_int, normalize_position)
- ✅ Match analytics tracking
- ✅ Player dataclass validation
- ✅ Roster parsing and validation
- ✅ Position normalization
- ✅ Invalid data handling

**Parser Tests** (`test_parsers.py`) - 12 tests
- ✅ Team roster parsing from Yahoo API responses
- ✅ Free agent/waiver wire parsing
- ✅ Handling malformed API responses
- ✅ Extracting player attributes (name, position, team, status)
- ✅ Ownership and injury data parsing

#### Integration Tests (8 tests)

**MCP Tool Flows** (`test_mcp_tools.py`) - 8 tests
- ✅ Complete league tool workflow (discover → info → standings)
- ✅ Roster parsing to lineup optimizer pipeline
- ✅ Token refresh and API status workflow
- ✅ Yahoo API response transformation pipeline
- ✅ Error recovery in multi-stage pipelines
- ✅ Cache behavior (hits and misses)

## Test Fixtures

Shared fixtures in `conftest.py`:

- `mock_env_vars`: Mock Yahoo API credentials
- `mock_yahoo_league_response`: Sample Yahoo leagues API response
- `mock_yahoo_roster_response`: Sample Yahoo roster API response
- `mock_yahoo_free_agents_response`: Sample Yahoo free agents response
- `mock_yahoo_standings_response`: Sample Yahoo standings response
- `mock_rate_limiter`: Mock rate limiter for testing
- `mock_response_cache`: Mock response cache
- `sample_roster_data`: Sample parsed roster data
- `sample_sleeper_rankings`: Sample Sleeper API rankings

## Testing Best Practices

### For New Features

When adding new features:

1. **Write tests first** (TDD approach when possible)
2. **Test edge cases**: Empty responses, malformed data, network errors
3. **Test the happy path**: Ensure normal operations work correctly
4. **Mock external dependencies**: Yahoo API, Reddit API, etc.
5. **Aim for 80%+ coverage** on critical paths

### Test Naming Convention

```python
class TestModuleName:
    def test_function_name_scenario(self):
        """Test description explaining what's being tested."""
        # Arrange
        # Act
        # Assert
```

### Async Test Example

```python
@pytest.mark.asyncio
async def test_async_function(self):
    """Test async function behavior."""
    result = await some_async_function()
    assert result == expected
```

### Mock Yahoo API Example

```python
@pytest.mark.asyncio
async def test_with_mock_api(self, mock_yahoo_roster_response):
    """Test using mocked Yahoo API response."""
    with patch("src.api.yahoo_client.yahoo_api_call") as mock_call:
        mock_call.return_value = mock_yahoo_roster_response
        result = await function_under_test()
        assert result is not None
```

## Continuous Integration

Tests are designed to run in CI/CD pipelines:

```bash
# Install dependencies
pip install -r requirements.txt

# Run tests with coverage
pytest tests/ --cov=src --cov=lineup_optimizer --cov-report=xml

# Check coverage threshold (optional)
pytest tests/ --cov-fail-under=80
```

## Adding New Tests

### 1. Create Test File

```python
"""Tests for new module."""

import pytest
from your_module import function_to_test

class TestNewFeature:
    def test_basic_functionality(self):
        """Test basic feature works."""
        result = function_to_test()
        assert result == expected
```

### 2. Add Fixtures (if needed)

In `conftest.py`:

```python
@pytest.fixture
def sample_data():
    """Provide sample test data."""
    return {"key": "value"}
```

### 3. Run New Tests

```bash
pytest tests/unit/test_new_file.py -v
```

## Troubleshooting

### Tests Fail with Import Errors

Ensure you're running from the project root:
```bash
cd /path/to/fantasy-football-mcp-server
pytest tests/
```

### Async Tests Not Running

Make sure `pytest-asyncio` is installed:
```bash
pip install pytest-asyncio
```

### Mock Issues

Use proper async mocking for aiohttp:
```python
# Create proper async context manager classes
class MockResponse:
    status = 200
    async def json(self):
        return {"data": "value"}

class MockSession:
    def get(self, *args, **kwargs):
        class Context:
            async def __aenter__(self):
                return MockResponse()
            async def __aexit__(self, *args):
                return None
        return Context()
```

## Future Test Improvements

- [ ] Add tests for draft evaluation algorithms
- [ ] Add tests for matchup analyzer
- [ ] Add tests for position normalizer
- [ ] Add tests for sleeper API integration
- [ ] Add performance/benchmark tests
- [ ] Add end-to-end tests with real API (optional, behind flag)
- [ ] Increase coverage for complex handlers (roster, draft, player)
- [ ] Add property-based testing with Hypothesis

## Test Markers

Available pytest markers:

- `@pytest.mark.unit`: Unit test
- `@pytest.mark.integration`: Integration test
- `@pytest.mark.slow`: Slow-running test
- `@pytest.mark.asyncio`: Async test

Filter by marker:
```bash
pytest tests/ -m "unit and not slow"
```
