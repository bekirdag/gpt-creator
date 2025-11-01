export function verifyCsrf(incomingToken: string | undefined, sessionToken: string | undefined): boolean {
  if (!incomingToken || !sessionToken) {
    return false;
  }
  return incomingToken === sessionToken;
}
