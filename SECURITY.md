# Security Policy

## Reporting

Do not disclose vulnerabilities in a public issue. Contact the repository maintainer privately with the affected version, reproduction steps, and impact.

## Secrets and Data

- Keep `QIANFAN_API_KEY` in server-side environment variables only.
- Never commit `.env`, SQLite files, uploaded datasets, or model responses containing sensitive data.
- LabelSpec does not encrypt its local SQLite workspace. Use operating-system access controls and an encrypted disk when processing sensitive data.
- Review Qianfan data handling and retention terms before sending production data.

