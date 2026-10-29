import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  if (mode === "production") {
    const required = [
      "VITE_API_BASE",
      "VITE_AUTH_MODE",
      "VITE_COGNITO_ISSUER",
      "VITE_COGNITO_CLIENT_ID",
    ];
    const missing = required.filter((name) => !env[name]?.trim());
    if (missing.length) {
      throw new Error(`Missing production frontend configuration: ${missing.join(", ")}`);
    }
    if (env.VITE_AUTH_MODE !== "cognito") {
      throw new Error("Production frontend builds must use VITE_AUTH_MODE=cognito.");
    }
    for (const name of ["VITE_API_BASE", "VITE_COGNITO_ISSUER"]) {
      if (new URL(env[name]).protocol !== "https:") {
        throw new Error(`${name} must use HTTPS in a production build.`);
      }
    }
  }

  return {
    plugins: [react()],
    server: { host: "127.0.0.1", port: 5173 },
  };
});
