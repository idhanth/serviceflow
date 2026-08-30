import { closeRoleContexts } from "./helpers";

/** Closes the browsers the role-scoped API clients kept open. */
export default async function globalTeardown() {
  await closeRoleContexts();
}
