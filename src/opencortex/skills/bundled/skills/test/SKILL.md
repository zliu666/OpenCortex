---
name: test
version: 1.0.0
description: Write and run tests for code.
author: OpenCortex Team
trigger_keywords:
  - test
  - "write tests"
  - "test coverage"
  - "unit test"
  - "integration test"
  - verify
required_tools:
  - bash
  - read_file
  - write_file
parameters:
  - name: test_framework
    type: string
    required: false
    description: Testing framework to use (auto-detected if not specified)
  - name: coverage_target
    type: integer
    required: false
    default: 80
    description: Target test coverage percentage
---

# Test

Write and run tests for code to ensure correctness and prevent regressions.

## When to use

Use this skill when the user asks to:
- Write tests for new or existing code
- Improve test coverage
- Verify behavior or functionality
- Test a bug fix (regression test)
- Ensure refactored code still works

## Workflow

1. **Understand what needs testing**:
   - **New feature**: Write unit tests for the happy path and edge cases
   - **Bug fix**: Write a regression test that would have caught the bug
   - **Refactor**: Ensure existing tests still pass
   - **Coverage gap**: Identify untested code paths and add tests

2. **Follow the project's testing patterns**:
   - Check existing tests for the framework (pytest, jest, go test, etc.)
   - Match naming conventions and file organization
   - Use existing fixtures, helpers, and test utilities
   - Follow the project's test structure (unit vs integration)

3. **Write effective tests**:
   - **Independence**: Each test can run alone without dependencies
   - **Determinism**: Same result every time (no randomness or external state)
   - **Speed**: Mock external services, use in-memory databases
   - **Clarity**: Test names should explain what they test
   - **Focus**: One assertion per test when possible
   - **Behavior**: Test what the code does, not how it does it

4. **Run the tests**:
   - Execute the test suite
   - Verify all tests pass
   - Check coverage if available
   - Fix any failing tests

5. **Handle edge cases**:
   - Test boundary conditions (empty, null, max values)
   - Test error conditions (exceptions, invalid input)
   - Test concurrency issues if applicable
   - Test with realistic data

## Rules

- **Test behavior, not implementation**: Focus on what the code does, not how
- **One assertion per test**: Keep tests focused and easy to debug
- **Descriptive names**: Test names should explain the scenario being tested
- **Don't test frameworks**: Avoid testing library or framework code
- **Mock at boundaries**: Mock external APIs, filesystem, network, databases
- **Avoid flaky tests**: Tests should be deterministic and reliable
- **Follow conventions**: Match the project's existing test patterns
- **Keep tests simple**: Complex test logic is itself hard to test

## Examples

### Example 1: Testing a new function

```markdown
User: Write tests for this discount calculation function

Agent: I'll write comprehensive tests for the discount calculation.

[Reads the function to understand its behavior]
[Checks existing test patterns]
[Writes tests:]

```python
def test_discount_none():
    """No discount should be applied for non-members."""
    assert calculate_discount(price=100, member_level=None) == 100

def test_discount bronze():
    """Bronze members get 5% discount."""
    assert calculate_discount(price=100, member_level="bronze") == 95

def test_discount_silver():
    """Silver members get 10% discount."""
    assert calculate_discount(price=100, member_level="silver") == 90

def test_discount_gold():
    """Gold members get 15% discount."""
    assert calculate_discount(price=100, member_level="gold") == 85

def test_discount_free():
    """Free items have no discount applied."""
    assert calculate_discount(price=0, member_level="gold") == 0

def test_discount_invalid_level():
    """Invalid member level raises error."""
    with pytest.raises(ValueError):
        calculate_discount(price=100, member_level="platinum")
```
```

### Example 2: Regression test for a bug fix

```markdown
User: I fixed a bug where division by zero wasn't handled. Write a test.

Agent: I'll write a regression test for the division by zero fix.

[Reads the fixed code]
[Writes a test that would have caught the bug:]

```python
def test_divide_by_zero():
    """Division by zero should return infinity or raise error."""
    # Before the fix, this would crash
    result = safe_divide(10, 0)
    assert result == float('inf')

def test_divide_normal():
    """Normal division should work correctly."""
    assert safe_divide(10, 2) == 5.0
```
```

### Example 3: Integration test

```markdown
User: Write integration tests for the user registration flow

Agent: I'll write integration tests for the complete registration flow.

[Understands the registration flow]
[Writes tests that cover the full flow:]

```python
def test_user_registration_success():
    """Successful registration creates user and sends welcome email."""
    response = client.post('/register', json={
        'email': 'test@example.com',
        'password': 'securepassword'
    })
    assert response.status_code == 201
    
    # Verify user was created
    user = db.query(User, email='test@example.com')
    assert user is not None
    
    # Verify welcome email was sent
    assert len(mock_email.send.calls) == 1

def test_user_registration_duplicate_email():
    """Registration with duplicate email should fail."""
    # Create existing user
    create_user(email='test@example.com')
    
    # Try to register with same email
    response = client.post('/register', json={
        'email': 'test@example.com',
        'password': 'anotherpassword'
    })
    assert response.status_code == 409
```
```

## Testing Best Practices

### Test Organization
- **Unit tests**: Test individual functions/classes in isolation
- **Integration tests**: Test multiple components working together
- **End-to-end tests**: Test complete user workflows
- **Keep them fast**: Most tests should run in milliseconds

### Test Naming
Use descriptive names that explain the scenario:
- `test_user_login_with_valid_credentials_succeeds`
- `test_user_login_with_invalid_password_fails`
- `test_empty_cart_returns_zero_total`

### Test Structure
Follow the Arrange-Act-Assert (AAA) pattern:
```python
def test_something():
    # Arrange: Set up the test
    input_value = 42
    
    # Act: Execute the code being tested
    result = process(input_value)
    
    # Assert: Verify the result
    assert result == expected_value
```

### Mocking Guidelines
- **Do mock**: External APIs, databases, filesystem, network calls
- **Don't mock**: The code you're testing, simple functions, value objects
- **Use fakes**: For external services, prefer fake implementations over mocks

### Coverage Goals
- Aim for 80%+ coverage for critical code paths
- Focus on testing complex logic over simple getters/setters
- Test edge cases and error conditions

## See also

- `debug` - Debugging failing tests
- `review` - Reviewing test code
- `commit` - Committing test changes
