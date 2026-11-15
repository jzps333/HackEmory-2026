"use client";

import { useEffect, useRef, useState } from "react";

interface DetectedCode {
  rawValue: string;
}

interface QRDetector {
  detect(source: HTMLVideoElement): Promise<DetectedCode[]>;
}

interface QRDetectorConstructor {
  new (options: { formats: string[] }): QRDetector;
}

type ScannerStatus = "starting" | "ready" | "unsupported" | "error";

export function QRScanner({
  onResult,
  onClose,
}: {
  onResult: (value: string) => void;
  onClose: () => void;
}) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const resultHandler = useRef(onResult);
  const [status, setStatus] = useState<ScannerStatus>("starting");
  const [message, setMessage] = useState("");

  useEffect(() => {
    resultHandler.current = onResult;
  }, [onResult]);

  useEffect(() => {
    let active = true;
    let animationFrame = 0;
    let stream: MediaStream | undefined;

    async function startCamera() {
      const Detector = (
        window as Window & { BarcodeDetector?: QRDetectorConstructor }
      ).BarcodeDetector;
      if (!Detector) {
        setStatus("unsupported");
        setMessage("QR camera scanning isn’t available in this browser. You can enter the link below instead.");
        return;
      }

      if (!navigator.mediaDevices?.getUserMedia) {
        setStatus("error");
        setMessage("This browser can’t access a camera. Enter the QR link below instead.");
        return;
      }

      try {
        const detector = new Detector({ formats: ["qr_code"] });
        stream = await navigator.mediaDevices.getUserMedia({
          audio: false,
          video: { facingMode: { ideal: "environment" } },
        });
        if (!active) {
          stream.getTracks().forEach((track) => track.stop());
          return;
        }

        const video = videoRef.current;
        if (!video) {
          throw new Error("The camera preview could not be started.");
        }
        video.srcObject = stream;
        await video.play();
        setStatus("ready");

        const scanFrame = async () => {
          if (!active || !video.videoWidth) {
            animationFrame = requestAnimationFrame(scanFrame);
            return;
          }
          try {
            const codes = await detector.detect(video);
            if (active && codes[0]?.rawValue) {
              resultHandler.current(codes[0].rawValue);
              return;
            }
          } catch {
            if (active) {
              setStatus("error");
              setMessage("We couldn’t read that QR code. Try adjusting the camera or enter the link below.");
            }
            return;
          }
          if (active) animationFrame = requestAnimationFrame(scanFrame);
        };
        animationFrame = requestAnimationFrame(scanFrame);
      } catch (error) {
        if (!active) return;
        setStatus("error");
        setMessage(
          error instanceof DOMException && error.name === "NotAllowedError"
            ? "Camera access was declined. You can enter the QR link below instead."
            : "We couldn’t start the camera. Check your camera permission or enter the link below.",
        );
      }
    }

    void startCamera();
    return () => {
      active = false;
      cancelAnimationFrame(animationFrame);
      stream?.getTracks().forEach((track) => track.stop());
      if (videoRef.current) videoRef.current.srcObject = null;
    };
  }, []);

  return (
    <section className="camera-panel" aria-label="QR camera scanner">
      <div className="camera-frame">
        <video ref={videoRef} className="camera-preview" playsInline muted />
        <span className="scan-frame" aria-hidden="true">
          <i />
          <i />
          <i />
          <i />
        </span>
        {status === "starting" && (
          <div className="camera-overlay">
            <span className="loading-spinner" aria-hidden="true" />
            <span>Starting camera…</span>
          </div>
        )}
        {status === "ready" && <span className="scan-line" aria-hidden="true" />}
      </div>
      <p className="camera-status" role={status === "error" ? "alert" : "status"}>
        {message || (status === "ready" ? "Point your camera at a QR code." : "")}
      </p>
      <button className="secondary-button camera-close" type="button" onClick={onClose}>
        Close camera
      </button>
    </section>
  );
}
