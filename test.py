import asyncio
import aiohttp
import time
import statistics

URL = "https://qgen.ramcoad.com/"

# Change these
CONCURRENT_USERS = 5000
DURATION = 60          # seconds
REQUEST_TIMEOUT = 20   # seconds


async def worker(session, results, stop_event):
    while not stop_event.is_set():
        start = time.perf_counter()

        try:
            async with session.get(URL) as response:
                await response.read()

                elapsed = time.perf_counter() - start

                results["requests"] += 1
                results["latencies"].append(elapsed)

                if 200 <= response.status < 400:
                    results["success"] += 1
                else:
                    results["errors"] += 1
                    results["status_codes"][response.status] = (
                        results["status_codes"].get(response.status, 0) + 1
                    )

        except Exception as e:
            results["requests"] += 1
            results["errors"] += 1
            results["exceptions"] += 1

        # Small delay prevents this from becoming an uncontrolled tight loop
        await asyncio.sleep(0)


async def main():
    results = {
        "requests": 0,
        "success": 0,
        "errors": 0,
        "exceptions": 0,
        "latencies": [],
        "status_codes": {},
    }

    stop_event = asyncio.Event()

    timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)

    connector = aiohttp.TCPConnector(
        limit=CONCURRENT_USERS * 2,
        ssl=True,
    )

    headers = {
        "User-Agent": "QGen-LoadTest/1.0",
        "Accept": "text/html,application/xhtml+xml",
    }

    print("=" * 60)
    print("QGEN LOAD TEST")
    print("=" * 60)
    print(f"Target       : {URL}")
    print(f"Users        : {CONCURRENT_USERS}")
    print(f"Duration     : {DURATION}s")
    print("=" * 60)

    async with aiohttp.ClientSession(
        timeout=timeout,
        connector=connector,
        headers=headers,
    ) as session:

        tasks = [
            asyncio.create_task(
                worker(session, results, stop_event)
            )
            for _ in range(CONCURRENT_USERS)
        ]

        start_time = time.perf_counter()

        # Print live statistics
        while time.perf_counter() - start_time < DURATION:
            await asyncio.sleep(5)

            elapsed = time.perf_counter() - start_time
            requests = results["requests"]
            rps = requests / elapsed if elapsed else 0

            print(
                f"[{elapsed:5.1f}s] "
                f"Requests: {requests:6d} | "
                f"Success: {results['success']:6d} | "
                f"Errors: {results['errors']:5d} | "
                f"RPS: {rps:7.2f}"
            )

        stop_event.set()

        await asyncio.gather(*tasks, return_exceptions=True)

    elapsed = time.perf_counter() - start_time

    print("\n" + "=" * 60)
    print("RESULTS")
    print("=" * 60)

    print(f"Total requests : {results['requests']}")
    print(f"Successful     : {results['success']}")
    print(f"Errors         : {results['errors']}")
    print(f"Exceptions     : {results['exceptions']}")
    print(f"Requests/sec   : {results['requests'] / elapsed:.2f}")

    if results["latencies"]:
        latencies = results["latencies"]

        print("\nLatency:")
        print(f"  Min          : {min(latencies) * 1000:.2f} ms")
        print(f"  Average      : {statistics.mean(latencies) * 1000:.2f} ms")
        print(f"  Max          : {max(latencies) * 1000:.2f} ms")

        sorted_latencies = sorted(latencies)

        def percentile(p):
            index = int(len(sorted_latencies) * p / 100)
            index = min(index, len(sorted_latencies) - 1)
            return sorted_latencies[index] * 1000

        print(f"  P50          : {percentile(50):.2f} ms")
        print(f"  P95          : {percentile(95):.2f} ms")
        print(f"  P99          : {percentile(99):.2f} ms")

    if results["status_codes"]:
        print("\nHTTP status codes:")

        for code, count in sorted(results["status_codes"].items()):
            print(f"  {code}: {count}")

    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())