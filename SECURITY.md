# Security policy

This project is intended only for systems you own, CTFs, laboratories, or targets for which you have explicit authorization.

The HTTP client enforces a global request budget, bounded concurrency, timeouts, limited retries, TLS verification by default, and a global request delay. Redirects are not followed.

The realtime console binds to loopback by default. Non-loopback binding requires an explicit opt-in flag, an explicit authentication token, and a TLS certificate/key pair. State-changing API requests require authentication and CSRF validation. Discovered identifiers are rendered with DOM text nodes, and sensitive-looking row values are masked before persistence unless explicitly revealed.

Do not submit real credentials, secrets, production data, session databases, or exported findings in issues. Report project vulnerabilities privately to the repository owner.
