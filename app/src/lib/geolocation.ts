import type { Coordinates } from "@/lib/onboarding";

export class LocationAccessError extends Error {
  constructor(
    message: string,
    readonly code: number | "unsupported",
  ) {
    super(message);
    this.name = "LocationAccessError";
  }
}

export function requestCurrentLocation(): Promise<Coordinates> {
  if (!("geolocation" in navigator)) {
    return Promise.reject(
      new LocationAccessError(
        "Location is not available in this browser. You can try another browser or device.",
        "unsupported",
      ),
    );
  }

  return new Promise((resolve, reject) => {
    navigator.geolocation.getCurrentPosition(
      ({ coords }) => {
        resolve({
          latitude: coords.latitude,
          longitude: coords.longitude,
        });
      },
      (error) => {
        switch (error.code) {
          case error.PERMISSION_DENIED:
            reject(
              new LocationAccessError(
                "Location permission was denied. Allow location access in your browser settings, then try again.",
                error.code,
              ),
            );
            break;
          case error.POSITION_UNAVAILABLE:
            reject(
              new LocationAccessError(
                "Your device could not determine your location. Check your connection and try again.",
                error.code,
              ),
            );
            break;
          case error.TIMEOUT:
            reject(
              new LocationAccessError(
                "The location request timed out. Please try again.",
                error.code,
              ),
            );
            break;
          default:
            reject(
              new LocationAccessError(
                "We couldn't access your location. Please try again.",
                error.code,
              ),
            );
        }
      },
      {
        enableHighAccuracy: true,
        maximumAge: 0,
        timeout: 15_000,
      },
    );
  });
}
