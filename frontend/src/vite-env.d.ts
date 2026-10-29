/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE?: string;
  readonly VITE_AUTH_MODE?: "local-demo" | "cognito";
  readonly VITE_COGNITO_ISSUER?: string;
  readonly VITE_COGNITO_CLIENT_ID?: string;
}
