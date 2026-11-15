export interface Coordinates {
  latitude: number;
  longitude: number;
}

export interface OnboardingData {
  fullName: string;
  email: string;
  phone: string;
  location: Coordinates | null;
  walletAddress: string | null;
  /** The user agreed that ScanSafe may FaceTime them to show a scanned page live. */
  facetimeOk: boolean;
}

export type OnboardingCompletionHandler = (
  data: OnboardingData,
) => void | Promise<void>;
