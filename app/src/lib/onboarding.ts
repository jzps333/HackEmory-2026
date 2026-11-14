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
}

export type OnboardingCompletionHandler = (
  data: OnboardingData,
) => void | Promise<void>;
