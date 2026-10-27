# 13 · Rerun the guides from scratch by script

To proceed step by step or resume an incomplete installation, use the [guided walkthrough](PASO-A-PASO.md). The rehearsal in this chapter is different: its `rebuild` operation removes resources and rebuilds the lab.

[Index](README.md) · Requires [00](00-entorno.md) · [Validation results](VALIDACION.md)

This rehearsal runs the Bash blocks from chapters 00–10, always including xAI, OpenAI and Claude, in dependency order. It extracts the commands directly from the Markdown and records the SHA-256 hash of each block it runs. Blocks that invoke a file run that file from the repository; chapter 04 uses separate commands for the runtime, groups and bootstrap. It does not call `demo.sh start`. Vault is configured through its CLI; external APIs are called with curl.

## 1. Prepare the inputs

Complete `.env` as described in 00 and start the container engine. To rerun with OpenAI, `OPENAI_PROJECT_ID`, `OPENAI_SERVICE_ACCOUNT_ID` and `OPENAI_IDENTITY_PROVIDER_ID` must be saved, along with the Admin API key and ngrok. For Claude, the five WIF IDs from [08](08-claude-spiffe.md) are kept and the administrative OAuth profile `lumen-admin` is prepared. The installation synchronizes the new public keys through the official API before the first exchange. External WIF resources are kept.

The test accounts are Cloud Directory users with an active password and no MFA required by an additional policy. The script stops if it encounters MFA, a password change or an unknown form. It does not bypass those controls or use the ROPC password grant. Perl parses the HTML received by curl; it does not drive a browser.

## 2. Remove and rebuild

### If the cluster was stopped

Removal needs to query Kubernetes and revoke the xAI leases in the previous
Vault. If the Mac or Podman restarted, recover that deployment first.
Check `podman machine list` and start the VM only if it is stopped:

```bash
podman machine start podman-machine-default
```

If `minikube status -p workshop` does not show the API server running:

```bash
minikube start -p workshop
```

A Vault using Shamir seals again when its pods restart. From Bash,
unseal the three replicas with the existing deployment's keys, without
reinitializing it or regenerating its certificates:

```bash
state="${LUMEN_STATE_DIR:-$HOME/.local/state/lumen-vault-demo}"
test -s "$state/vault/cluster-keys.json"
for pod in vault-0 vault-1 vault-2; do
  jq '{key:.unseal_keys_b64[0]}' "$state/vault/cluster-keys.json" |
    kubectl --context workshop -n vault exec -i "$pod" -- \
      vault write -format=json sys/unseal - > /dev/null || break
done
kubectl --context workshop -n vault wait --for=condition=Ready \
  pod/vault-0 pod/vault-1 pod/vault-2 --timeout=120s
```

Continue only if the three replicas are Ready. If the keys are missing, recover
the corresponding bootstrap before removing resources: deleting the Vault
volumes would prevent revoking the external keys that its leases still manage.
The `bash demo.sh remove --dry-run` simulation inventories resources, but it does not prove
that Vault is unsealed and does not perform the revocation.

### Run the cycle

From the workspace root:

```bash
bash scripts/manual/rehearse.sh rebuild
```

The command inventories the removal with `demo.sh remove --dry-run`, stops the registered manual processes, runs `demo.sh remove`, checks that the three namespaces are gone and installs from the guide blocks. The Lumen processes and the forwards stay running so the demo can be shown afterwards.

On macOS, `caffeinate -ims` inhibits idle, disk and system sleep for the duration of the rehearsal; inhibiting system sleep requires AC power. Step 01 checks the VM clock and synchronizes Podman if it fell behind after an earlier sleep. Keep the computer open and plugged in during the run. A forced sleep or closing the lid can interrupt the network and let five-minute credentials expire; that rehearsal is considered failed, and it is not hidden as a successful result.

The following are deleted: the Lumen resources in the Kubernetes namespaces `vault`, `mysql` and `lumen-observability`, their volumes, the Lumen apps/STS/users/groups in Verify and the operational state removed by `remove`. The following are kept: `.env`, Verify's administrative client and shared RAR schema, the OpenAI project/account/mapping, the Minikube profile, the image cache and resources unrelated to Lumen. Therefore, this rehearsal rebuilds the lab on top of its prepared external accounts; it does not recreate those accounts.

Audit is enabled immediately after initializing Vault. All three branches are always configured. `LUMEN_MODEL_PROVIDER` only sets the banner's initial provider; it does not control which branches are installed or verified. Before removing resources, the credentials and external IDs of all three integrations must be present. The conditional steps that create the OpenAI project/account are skipped when their IDs are reused.

`rebuild` and `install` finish the local installation, generate `claude-jwks.json` inside the run directory and synchronize the existing issuer. The result is checked by a subsequent API read. Continue with the real tests:

```bash
bash scripts/manual/rehearse.sh verify
```

The path of the pending report is saved in `$MANUAL/pending-verification-run`. When `verify` runs in a new terminal, it reuses that path, finalizes the cycle result and only then removes the pending marker. If validation fails, the marker is kept for diagnosis and retry. To verify a different deployment, set `MANUAL_RUN` explicitly to a new directory.

Installation and functional verification run as separate phases. The `verify` phase runs Claude's blocks 8–14, preceded by its environment block, including inference and the negative replay, before the general walkthroughs.

The port-forward, ngrok, JWKS publishing and Lumen commands need running
processes. In a normal terminal, keep the corresponding terminals open
or use the rehearsal's background mechanism. `nohup` protects against SIGHUP,
but not against a runner that kills its entire process tree when a
session closes. If you use one of those runners, launch the same commands in independent
sessions and check `/health`, the ports and the public JWKS again
after closing the provisioning terminal.

### `Released` volumes after restarting Minikube

In the October 23 rebuild, the namespaces disappeared but the ten PVs
stayed `Released`, with a `Delete` policy. The provisioner logged
`identity annotation on PV does not match ours`: its identity had changed
on restart. This is the behavior described in
[Minikube issue #16140](https://github.com/kubernetes/minikube/issues/16140).
Removal waits for the PVs to disappear; until that happens, it keeps the
recovery keys and does not mark the deletion as complete.

Check the cause before acting:

```bash
kubectl --context workshop get pv
kubectl --context workshop -n kube-system logs storage-provisioner --tail=100
```

For this specific case, on the **single-node workshop** profile, you can
remove each inventoried volume's hostPath directory and then its PV
object. The following block requires that the three namespaces no longer exist, validates all
paths before deleting and only accepts the ten PVC names of this demo.
Do not remove finalizers or delete only the PV object: that could leave the
previous data available to the next deployment.

From Bash, with the current removal's `remove-plan.json`:

```bash
set -euo pipefail
state="${LUMEN_STATE_DIR:-$HOME/.local/state/lumen-vault-demo}"
test -s "$state/remove-plan.json"
test -z "$(kubectl --context workshop get namespace vault mysql lumen-observability --ignore-not-found -o name)"
kubectl --context workshop get nodes -o json |
  jq -e '.items|length==1 and .[0].metadata.name=="workshop"' >/dev/null
kubectl --context workshop get pv -o json > "$state/pv-recovery.json"
jq -e --slurpfile plan "$state/remove-plan.json" '
  [.items[] | select(.metadata.name as $name | any($plan[0].volumes[]; .name==$name))] |
  if length>0 and all(.[];
    .status.phase=="Released" and .spec.persistentVolumeReclaimPolicy=="Delete" and
    .metadata.annotations["pv.kubernetes.io/provisioned-by"]=="k8s.io/minikube-hostpath" and
    ([.spec.claimRef.namespace,.spec.claimRef.name]|join("/")|
      test("^(vault/(data|audit)-vault-[012]|mysql/data-mysql-enterprise-0|lumen-observability/(grafana|loki|tempo)-data)$")) and
    .spec.hostPath.path==("/tmp/hostpath-provisioner/"+.spec.claimRef.namespace+"/"+.spec.claimRef.name))
  then . else error("Incompatible inventory: stop the recovery") end
' "$state/pv-recovery.json" > "$state/pv-recovery-targets.json"
jq -r '.[]|[.metadata.name,.metadata.uid,.spec.hostPath.path]|@tsv' \
  "$state/pv-recovery-targets.json" > "$state/pv-recovery-targets.tsv"
while IFS=$'\t' read -r name uid path; do
  kubectl --context workshop get pv "$name" -o json |
    jq -e --arg uid "$uid" '.metadata.uid==$uid and .status.phase=="Released"' >/dev/null
  minikube ssh -p workshop -- \
    "test ! -L '$path' && sudo rm -rf -- '$path' && test ! -e '$path'" </dev/null
  kubectl --context workshop delete pv "$name" --wait=true --timeout=30s
done < "$state/pv-recovery-targets.tsv"
```

If `remove` was still waiting, it continues when the last volume disappears.
If it had already run out of time, repeat `bash demo.sh remove` to complete the local
removal, check `last-remove.json` and start the installation. Do not run another
removal in parallel. In this case, the absence of each directory inside the node
was also checked; the namespace disappearing is not enough on its own.

## 3. Validate the walkthroughs by script

After the key synchronization during installation, `verify` runs these tests:

- Reader, writer and supervisor login through Authorization Code + PKCE, with independent cookies, `state`, nonce and signature/issuer/audience/expiration validation.
- Nine Vault permissions per profile, SQL catalog, five-step application with synthetic data, idempotency, masked read and authorized reveal.
- Database and decrypt blocks with earlier and new JWTs; removal of the block and reuse of the still-valid JWT.
- Deep Agents with the OBO catalog, Tavily search and rejection of non-energy questions.
- Per-session selection of OpenAI, xAI and Claude over a single catalog: catalog/Tavily tools, scope, the trace's model and the corresponding SPIFFE identity. xAI additionally checks the reauthorized cache, replacement before expiration, blocking and revocation.
- Traces in Tempo and Vault request/response pairs in Loki, correlated with each action.

The functional operations use the real services of the Python application, without mocks. Provisioning and policy changes still use Bash, curl and the Vault CLI. This test does not visually inspect the CSS or press NiceGUI buttons; those visual walkthroughs are described in [10](10-aplicacion.md).

To repeat only the verifications on an active manual installation:

```bash
bash scripts/manual/rehearse.sh verify
```

Each run saves a synthetic application and issues temporary credentials. The blocks are removed when their tests finish, even if an assertion inside them fails.

## 4. Read the evidence and stop the processes

The command prints the `docs/runs/<date>-manual-script/` directory. `installation.json` contains the blocks and their hashes; `workflows.json`, the assertions and trace IDs. A full cycle adds `before.json`, `after.json`, the removal inventory and `result.json`. The latter is only created after both phases finish, and it requires namespaces with new UIDs and all checks passing.

Detailed logs, cookies, tokens and passwords are stored in `~/.local/state/lumen-vault-demo/manual/`, with private permissions. The rerun archives that directory in `manual-archives/` before recreating it; these private files must not be published either. A failure stops the run and leaves the logs for diagnosis: it does not automatically resend creation POSTs. The Verify inventory during removal allows two GET retries on transient errors; it does not automatically repeat POST or DELETE. The clock is checked at the start, before configuring each model provider and before the workflows.

To stop only the processes started by this rehearsal and keep the resources:

```bash
bash scripts/manual/stop.sh
```

Implementation: [runner](../../scripts/manual/rehearse.sh), [block installation](../../scripts/manual/install.sh), [OIDC login](../../scripts/manual/oidc-login.sh) and [functional tests](../../scripts/manual/workflows.py).

## Check the guides without deploying

`python3 scripts/manual/validate.py` checks the local links and the syntax of all Bash blocks and scripts; it updates `docs/manual/validacion.json`. The tests `cd chatbot && /tmp/vault-chatbot-venv/bin/python -m pytest -q tests/test_manual_configuration.py` run the catalog blocks against a simulated Vault and check the planning and resumption of the rehearsal. They do not recreate infrastructure or issue real credentials. These checks do not replace the full cycle with its external services.
