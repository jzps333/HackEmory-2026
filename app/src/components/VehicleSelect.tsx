"use client";

import { useState, type FormEvent } from "react";
import type { Vehicle, VehicleType } from "@/lib/appStorage";
import { createVehicle } from "@/services/appServices";

const vehicleTypes: Exclude<VehicleType, "">[] = ["Car", "SUV", "Truck", "Motorcycle", "Other"];

export function VehicleSelect({
  vehicles,
  selectedVehicleId,
  onAdd,
  onContinue,
}: {
  vehicles: Vehicle[];
  selectedVehicleId: string;
  onAdd: (vehicle: Vehicle) => void;
  onContinue: (vehicle: Vehicle) => void;
}) {
  const [selectedId, setSelectedId] = useState(selectedVehicleId);
  const [adding, setAdding] = useState(vehicles.length === 0);
  const [plate, setPlate] = useState("");
  const [nickname, setNickname] = useState("");
  const [type, setType] = useState<VehicleType>("");
  const [error, setError] = useState("");

  function addVehicle(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    if (!form.reportValidity()) return;
    if (!plate.trim()) {
      setError("Enter the license plate.");
      return;
    }
    const vehicle = createVehicle(plate, nickname, type);
    onAdd(vehicle);
    setSelectedId(vehicle.id);
    setAdding(false);
    setPlate("");
    setNickname("");
    setType("");
    setError("");
  }

  function continueFlow() {
    const vehicle = vehicles.find((item) => item.id === selectedId);
    if (!vehicle) {
      setError("Choose a vehicle before continuing.");
      return;
    }
    onContinue(vehicle);
  }

  return (
    <section className="screen-content">
      <div className="screen-heading">
        <span className="eyebrow">YOUR VEHICLE</span>
        <h1>Which car are you in?</h1>
        <p>Choose a saved vehicle or add one now.</p>
      </div>
      {vehicles.length > 0 && (
        <label className="field">
          <span>Saved vehicles</span>
          <select
            value={selectedId}
            onChange={(event) => {
              setSelectedId(event.target.value);
              setError("");
            }}
          >
            <option value="">Choose a vehicle</option>
            {vehicles.map((vehicle) => (
              <option value={vehicle.id} key={vehicle.id}>
                {vehicle.nickname ? `${vehicle.nickname} · ` : ""}{vehicle.plate}
              </option>
            ))}
          </select>
        </label>
      )}
      {!adding && (
        <button type="button" className="text-button add-vehicle-link" onClick={() => setAdding(true)}>
          + Add a vehicle
        </button>
      )}
      {adding && (
        <form className="vehicle-form" onSubmit={addVehicle}>
          <div className="form-section-heading">
            <h2>Add a vehicle</h2>
            {vehicles.length > 0 && (
              <button type="button" className="text-button" onClick={() => setAdding(false)}>Cancel</button>
            )}
          </div>
          <label className="field">
            <span>License plate</span>
            <input
              autoComplete="off"
              required
              maxLength={12}
              value={plate}
              onChange={(event) => setPlate(event.target.value)}
              placeholder="ABC 1234"
            />
          </label>
          <label className="field">
            <span>Nickname <small>Optional</small></span>
            <input
              autoComplete="off"
              maxLength={30}
              value={nickname}
              onChange={(event) => setNickname(event.target.value)}
              placeholder="Blue Honda"
            />
          </label>
          <label className="field">
            <span>Vehicle type <small>Optional</small></span>
            <select value={type} onChange={(event) => setType(event.target.value as VehicleType)}>
              <option value="">Select a type</option>
              {vehicleTypes.map((option) => <option value={option} key={option}>{option}</option>)}
            </select>
          </label>
          {error && <p className="form-error" role="alert">{error}</p>}
          <button className="secondary-button full-button" type="submit">Save vehicle</button>
        </form>
      )}
      {error && !adding && <p className="form-error" role="alert">{error}</p>}
      {!adding && (
        <button className="primary-button full-button" type="button" onClick={continueFlow}>
          Continue
        </button>
      )}
      <p className="fine-print">Vehicles are saved only in this browser.</p>
    </section>
  );
}
