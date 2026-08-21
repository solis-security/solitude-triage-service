# Extra CA certificates for the image build

Drop any additional root CA here as a `.crt` file (PEM encoded) and rebuild.
Everything in this directory is installed into the image's trust store, and
pip is pointed at it, so `docker compose build` works on networks that
intercept TLS — corporate proxies such as Zscaler, Netskope or Cloudflare
WARP Gateway.

Without this, the build fails at `pip install` with:

```
SSLError(SSLCertVerificationError(1, '[SSL: CERTIFICATE_VERIFY_FAILED]
certificate verify failed: self-signed certificate in certificate chain'))
```

On macOS, export your proxy's root CA with:

```bash
security find-certificate -a -p /Library/Keychains/System.keychain > certs/corp-ca.crt
```

`.crt` files here are gitignored — do not commit your organisation's
certificate. This directory is empty by default and the build is unaffected.
