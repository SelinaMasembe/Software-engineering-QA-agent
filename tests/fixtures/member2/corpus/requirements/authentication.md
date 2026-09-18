# Authentication requirements

REQ-AUTH-01 Reject an incorrect password

The authentication service must reject an incorrect password without creating a
user session. The result must distinguish invalid credentials from an
unavailable authentication service so a caller can retry appropriately.

REQ-AUTH-02 Lock an account after repeated failures

After five consecutive failed attempts for the same username, the service must
lock the account and return a lockout reason. A successful login resets the
failure counter to zero.

REQ-AUTH-03 Never log credential material

No password, token, or session identifier may appear in an application log
entry. Failure messages reference the username only.
