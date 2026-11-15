import uvicorn

if __name__ == "__main__":
    # Container entrypoint: Compose publishes the port on the internal backend network only.
    uvicorn.run("melorin.app:app", host="0.0.0.0", port=8000, reload=False)  # nosec B104
