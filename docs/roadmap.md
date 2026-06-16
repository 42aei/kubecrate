# Roadmap

## Context

Kubecrate has a broad vision and a narrow first path.

The broad vision is cluster-provider agnostic: any conforming Kubernetes cluster should eventually work. The narrow first path is kind-first so the initial work can stay concrete and testable.

## Near-term direction

The early roadmap is mostly about reducing ambiguity.

### 1. Define the install flow

Before adding implementation, the project needs a clear view of what point at a cluster and install means in practice.

That includes the boundary between bootstrap installation and GitOps-managed operation.

### 2. Define the local reference workflow

kind is the first local and reference path.

That does not change the long-term provider-agnostic goal, but it gives the project a realistic environment for the first installable slices.

### 3. Choose the minimal component set

The platform should start with the smallest useful set of platform services.

If a component does not help establish the baseline or validate the first installable slice, it should wait.

### 4. Create the first installable slice

The first real slice should be reviewable and useful on its own.

It should prove a small end-to-end path rather than building several horizontal layers in parallel.

## Likely sequence

The current expected order is:

1. define repository and documentation structure
2. define install flow and kind-first local workflow
3. define bootstrap-to-GitOps lifecycle handling
4. define the platform services and application services model in working detail
5. choose the minimal component set
6. build the first installable slice

## What is intentionally not in scope yet

This first pass does not try to settle every future component, provider path, or production concern.

The goal is to create enough structure to make the next implementation proposal small and reviewable.
