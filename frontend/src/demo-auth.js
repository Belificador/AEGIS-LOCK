const DEMO_CREDENTIALS = Object.freeze([
  Object.freeze({ username: "operador", password: "AegisOperador2026!", role: "operator" }),
  Object.freeze({ username: "admin", password: "AegisAdmin2026!", role: "admin" }),
]);

export function validateDemoCredentials(username, password) {
  const account = DEMO_CREDENTIALS.find((item) =>
    String(username).trim().toLocaleLowerCase("es") === item.username && password === item.password,
  );
  if (!account) throw new Error("Usuario o contraseña incorrectos.");
  return { username: account.username, role: account.role };
}
