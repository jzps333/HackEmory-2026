export interface Coordinates {
  latitude: number;
  longitude: number;
}

export interface OnboardingData {
  firstName: string;
  lastName: string;
  email: string;
  phone: string;
}

export type OnboardingCompletionHandler = (
  data: OnboardingData,
) => void | Promise<void>;
