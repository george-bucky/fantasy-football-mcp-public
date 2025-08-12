# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 1.0.x   | :white_check_mark: |
| < 1.0   | :x:                |

## Reporting a Vulnerability

We take security seriously. If you discover a security vulnerability, please follow these steps:

### DO NOT

- **Do not** create a public GitHub issue
- **Do not** disclose the vulnerability publicly until it has been addressed

### DO

1. **Report privately** via GitHub Security Advisories (if available) or email the maintainer
2. **Include details**:
   - Description of the vulnerability
   - Steps to reproduce
   - Potential impact
   - Suggested fix (if any)

### What to Expect

- **Acknowledgment**: Within 48 hours
- **Initial Assessment**: Within 1 week
- **Resolution Timeline**: Depends on severity
  - Critical: 1-2 weeks
  - High: 2-4 weeks
  - Medium/Low: 4-8 weeks

## Security Best Practices

### For Users

1. **API Credentials**
   - Never commit `.env` files
   - Store tokens securely
   - Rotate tokens regularly
   - Use environment variables

2. **Yahoo API Keys**
   - Create app-specific credentials
   - Limit scope to fantasy sports only
   - Monitor usage regularly
   - Revoke unused apps

3. **Reddit API (Optional)**
   - Use read-only permissions when possible
   - Don't share Reddit passwords
   - Use OAuth instead of passwords

### For Contributors

1. **Code Review**
   - Check for hardcoded credentials
   - Validate all inputs
   - Use parameterized queries
   - Follow OWASP guidelines

2. **Dependencies**
   - Keep dependencies updated
   - Review dependency security advisories
   - Use `pip audit` or similar tools

3. **Error Handling**
   - Don't expose sensitive data in errors
   - Log security events appropriately
   - Implement rate limiting

## Known Security Considerations

### Token Storage
- Access tokens are stored in memory during runtime
- Refresh tokens must be securely stored
- Consider using system keyring for production

### API Rate Limiting
- Implement proper rate limiting to prevent abuse
- Monitor for unusual activity patterns
- Use exponential backoff for retries

### Data Privacy
- League data may contain personal information
- Handle user data according to privacy laws
- Allow users to control their data

## Security Tools

Recommended tools for security scanning:

```bash
# Check for known vulnerabilities in dependencies
pip install safety
safety check

# Audit Python packages
pip install pip-audit
pip-audit

# Static security analysis
pip install bandit
bandit -r . -f json -o bandit-report.json
```

## Compliance

This project aims to comply with:
- Yahoo Developer Terms of Service
- Reddit API Terms
- GDPR (for EU users)
- CCPA (for California users)

## Contact

For security concerns, please contact the maintainers through:
- GitHub Security Advisories (preferred)
- Private message to repository maintainers

Thank you for helping keep Fantasy Football MCP secure!