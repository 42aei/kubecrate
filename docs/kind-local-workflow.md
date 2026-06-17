# Kind-first local workflow

This document defines the durable local reference workflow for Kubecrate.

Its purpose is to keep the first development, testing, demo, and early install work on a small and repeatable path. It is the reference workflow for the first installable slices, but it does not redefine the long-term goal of cluster-provider agnostic operation.

## Purpose and boundary

The kind-first local path is a local reference workflow.

It exists so Kubecrate can validate `point at a cluster and install` on a concrete cluster before broader provider paths are defined.

The boundary is simple:

- local cluster creation happens before Kubecrate bootstrap installation
- Kubecrate bootstrap installation starts when a Kubernetes API is reachable and the operator or calling tool has usable permissions

Cluster creation is local setup, not part of the Kubecrate bootstrap installation contract.

## Conceptual phases

The local reference workflow has four conceptual phases.

### 1. Local setup

The operator prepares a local Kubernetes cluster through kind and confirms that the cluster is reachable.

Any local credentials, kubeconfig access, and operator-supplied secret trust material needed for early platform services are prepared here.

### 2. Bootstrap installation

Kubecrate bootstrap installation begins only after the local setup boundary is satisfied.

At this stage, the operator or calling tool points at a cluster and install starts in the contract sense described in the bootstrap installation document. The goal is not to finish platform assembly. The goal is to establish the handoff into GitOps-managed operation.

Bootstrap installation remains a lifecycle phase. It is not a separate category alongside platform services and application services.

### 3. GitOps handoff reached

Bootstrap installation is complete when the cluster reaches the defined handoff condition:

- a GitOps controller is running
- the controller is bound to a Git source
- the initial structure can reconcile platform services and application services

This is the evidence point for the local reference workflow.

### 4. GitOps-managed operation

After handoff, ongoing reconciliation moves into GitOps-managed operation.

From that point, platform services and application services are managed through GitOps according to the two-axis model.

## Inputs and outputs

### Inputs

The kind-first local path assumes these conceptual inputs:

- local Kubernetes access to a reachable cluster API
- permissions for the operator or calling tool to perform bootstrap installation
- GitOps source information
- operator-supplied secret trust material if a bootstrap or early platform service needs it

These inputs are still tool-neutral. The local reference workflow does not require a Kubecrate-specific interface.

### Output and handoff evidence

The expected output of the workflow is not a finished platform. It is a reached handoff into GitOps-managed operation.

That handoff is evidenced by the following non-runnable signals:

- the GitOps controller is running in the cluster
- the controller is bound to the intended Git source
- the initial structure for platform services and application services can reconcile

## What this workflow is for

This workflow is the reference path for:

- development and testing of early install behavior
- small demos of the install and handoff model
- first installable slices that need a concrete but limited environment

It should stay simple enough that less experienced platform engineers can understand where local setup ends and where bootstrap installation begins.

## Non-goals and deferred decisions

This document does not define:

- runnable manifests, scripts, charts, or commands
- a final component set for platform services or application services
- a final repository layout for GitOps-managed operation
- a provider-specific product boundary beyond the kind-first local path as the first reference workflow
- a final packaging choice for bootstrap installation
- a final GitOps controller choice

Helm and common GitOps controllers may remain likely candidates for later validation, but this document does not make those choices final.

## Relationship to the broader project direction

The kind-first local path is the first local reference workflow, not the only future workflow.

It keeps the project concrete while preserving the broader goal of cluster-provider agnostic operation. Later provider paths should preserve the same bootstrap installation boundary, the same GitOps handoff condition, and the same separation between lifecycle phase and workload category.
