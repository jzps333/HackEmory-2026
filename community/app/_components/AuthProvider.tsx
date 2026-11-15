"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { ApiError, errorText } from "@/lib/api";
import { clearToken, getMe, logout, maskPhone, readToken, saveToken } from "@/lib/auth";

type Status = "checking" | "signed_out" | "signed_in" | "error";

type Auth = {
  status: Status;
  /** e.g. "•••9861" */
  phoneMasked: string;
  /** Set when the check on load failed for a reason other than a dead session. */
  error: string | null;
  /** Shown on the sign-in card, e.g. after a 401. */
  notice: string | null;
  /** Read the token for an API call. Never render or log it. */
  token: () => string | null;
  completeSignIn: (token: string, phone: string) => void;
  signOut: () => Promise<void>;
  /** A /me/* call answered 401: forget the token and show the sign-in card. */
  expired: () => void;
  recheck: () => void;
};

const AuthContext = createContext<Auth | null>(null);

export function useAuth(): Auth {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth needs <AuthProvider>");
  return ctx;
}

export default function AuthProvider({ children }: { children: React.ReactNode }) {
  const [status, setStatus] = useState<Status>("checking");
  const [phoneMasked, setPhoneMasked] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const tokenRef = useRef<string | null>(null);
  const seq = useRef(0);

  const forget = useCallback((why: string | null) => {
    seq.current++;
    tokenRef.current = null;
    clearToken();
    setPhoneMasked("");
    setError(null);
    setNotice(why);
    setStatus("signed_out");
  }, []);

  const check = useCallback(async () => {
    const mine = ++seq.current;
    const token = readToken();
    tokenRef.current = token;
    if (!token) {
      setStatus("signed_out");
      return;
    }
    setStatus("checking");
    setError(null);
    try {
      const me = await getMe(token);
      if (mine !== seq.current) return;
      if (me.signedIn) {
        setPhoneMasked(me.phoneMasked || "•••");
        setStatus("signed_in");
      } else {
        forget("Your sign-in ended. Sign in again to see your apps.");
      }
    } catch (e) {
      if (mine !== seq.current) return;
      if (e instanceof ApiError && e.status === 401) {
        forget("Your sign-in ended. Sign in again to see your apps.");
      } else {
        setError(`Couldn't check your sign-in. ${errorText(e)}`);
        setStatus("error");
      }
    }
  }, [forget]);

  useEffect(() => {
    check();
  }, [check]);

  const completeSignIn = useCallback(
    (token: string, phone: string) => {
      const mine = ++seq.current;
      tokenRef.current = token;
      saveToken(token);
      setPhoneMasked(maskPhone(phone));
      setError(null);
      setNotice(null);
      setStatus("signed_in");
      // Take the API's own masking when it answers; keep the local one if it can't.
      getMe(token)
        .then((me) => {
          if (mine !== seq.current) return;
          if (!me.signedIn) forget("That sign-in didn't stick. Send a new code.");
          else if (me.phoneMasked) setPhoneMasked(me.phoneMasked);
        })
        .catch((e) => {
          if (mine === seq.current && e instanceof ApiError && e.status === 401) {
            forget("That sign-in didn't stick. Send a new code.");
          }
        });
    },
    [forget],
  );

  const signOut = useCallback(async () => {
    const token = tokenRef.current;
    if (token) {
      try {
        await logout(token);
      } catch {
        /* the token is dropped here either way */
      }
    }
    forget(null);
  }, [forget]);

  const expired = useCallback(() => forget("Your sign-in ended. Sign in again to see your apps."), [forget]);

  const value = useMemo<Auth>(
    () => ({
      status,
      phoneMasked,
      error,
      notice,
      token: () => tokenRef.current,
      completeSignIn,
      signOut,
      expired,
      recheck: check,
    }),
    [status, phoneMasked, error, notice, completeSignIn, signOut, expired, check],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
