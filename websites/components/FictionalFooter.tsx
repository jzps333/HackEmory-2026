/** Small visible marker on every deliberately "scammy" demo page. */
export default function FictionalFooter() {
  return (
    <p
      className="demo-fictional-footer"
      style={{ margin: 0, padding: "10px 16px", textAlign: "center", fontSize: 12, color: "#555", background: "#f4f4f4" }}
    >
      ScanSafe demo — fictional
    </p>
  );
}
