# Security scope

Early local-only software for a trusted operator. Both listeners bind IPv4 loopback. Administration requires a per-state-directory bearer token. The state directory is mode 0700 and new token files mode 0600. Do not expose the admin port through a proxy/tunnel or share state directories. Deploy authority is effectively local command execution.

Do not place credentials in manifest arguments: status/history may contain those arguments. No secrets, real application data, state databases, tokens, process identities or environments belong in Git. Example data and retained measurements are synthetic.

The MVP does not sandbox workers or defend against another malicious process under the same user. PID plus creation-time checks reduce accidental PID-reuse hazards; they are not a kernel security boundary. Use an external service manager/OS controls for production isolation and resource caps.

Report vulnerabilities privately through [GitHub private vulnerability reporting](https://github.com/andrew29mo/shiftstead/security/advisories/new); do not include secrets in public issues. This MVP makes no availability, production-hardening or full HTTP-proxy compatibility guarantee.
