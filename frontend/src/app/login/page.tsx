"use client";

import {useRouter} from "next/navigation";
import {useAuthStore} from "@/shared/auth/auth-store";

export default function LoginPage() {
  const router = useRouter();
  const {email, password, status, error, setEmail, setPassword, login} = useAuthStore();
  return (
    <main className="login">
      <form
        className="panel"
        onSubmit={async (event) => {
          event.preventDefault();
          await login();
          if (useAuthStore.getState().status === "authenticated") router.push("/map");
        }}
      >
        <h1>Merchant Onboarding</h1>
        <label>
          账号
          <input className="field" value={email} onChange={(event) => setEmail(event.target.value)} />
        </label>
        <label>
          密码
          <input className="field" type="password" value={password} onChange={(event) => setPassword(event.target.value)} />
        </label>
        <button className="primary" type="submit" disabled={status === "loading"}>
          登录
        </button>
        {error ? <p role="alert">{error}</p> : null}
      </form>
    </main>
  );
}
