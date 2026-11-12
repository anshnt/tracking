# Guacamole connection policy

Files:

- `connection-template.json`: standard profile (copy out blocked, paste in allowed).
- `connection-template-restricted.json`: restricted profile (copy and paste both blocked).
- `provision-connection.sh`: creates a connection per employee and grants READ to that one user only.
- `guacamole.properties.example`: SAML and database property names.

Both templates are RDP with TLS, certificate verification on, and no drive, print, SFTP,
upload, download or microphone. They set no recording path: screen recording is out of scope.
`username`/`password` are intentionally absent so the employee is prompted for the VM credential
(single sign-on to RDP is not implemented; planned).

## Clipboard semantics

Guacamole names the direction from the user's point of view:

| Parameter | Blocks | Meaning |
| --- | --- | --- |
| `disable-copy=true` | remote -> local | Text selected in the workspace cannot be copied to the employee's laptop. This is the data-leaves control. |
| `disable-paste=true` | local -> remote | The employee's laptop clipboard cannot be pasted into the workspace. |

Chosen policy: standard profile blocks copy, allows paste (so commands and snippets can be brought in);
restricted profile blocks both. Limits to state honestly: this stops clipboard sync, not the display.
A person can still read, photograph or retype what is on screen. The remote OS is configured as a second
layer (xrdp `RestrictOutboundClipboard`, see the `workspace_vm` role), so a direct RDP client that bypasses
Guacamole is also constrained, and the firewall only lets guacd reach port 3389 in the first place.
`disable-download`/`disable-upload` cover the file transfer paths of the gateway; with `enable-drive=false`
and `enable-sftp=false` there is no file channel to apply them to, they are defence in depth.

## Certificate pinning

`ignore-cert=false` makes guacd verify the xrdp certificate against its trust store. xrdp certs are
self-signed, so the `workspace_vm` role writes the fingerprint to `/etc/xrdp/cert.fingerprint` in Guacamole's format
(`SHA256:AB:CD:...`, uppercase, 32 colon-separated bytes; `provision-connection.sh` and `tests/validate.py` reject anything else) and the
template carries it in `cert-fingerprints`. VERIFY that Guacamole 1.6.0's RDP parameter list includes
`cert-fingerprints` (check the 1.6.0 manual, "RDP > Authentication & Security"); if not, put the
CA that signs the xrdp certs into guacd's trust store instead. Never set `ignore-cert=true`.

## Access

`provision-connection.sh` grants one connection to one user. It creates the user row first (random unusable
password, SAML only), updates the connection on a re-run instead of duplicating it, and deletes a connection it just
created if the grant fails. Employees get no system permissions. The
bootstrap admin comes from `compose/postgres/guacamole-bootstrap.sql`; the stock `guacadmin` account is disabled.
