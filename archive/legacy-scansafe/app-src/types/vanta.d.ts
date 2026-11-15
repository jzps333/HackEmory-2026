// Vanta's UMD builds (vanta/dist/vanta.<effect>.min.js) export one effect function each.
declare module "vanta/dist/*" {
  const effect: (options: Record<string, unknown>) => { destroy: () => void };
  export default effect;
}
