"""A2A Multi-Agent Concurrent Test: 5 agents × 5-step chained calculation."""

import httpx
import asyncio
import json
import time

BASE = "http://127.0.0.1:8765"

# 5个不同的计算题，每题5步，上一步结果参与下一步
CALC_QUESTIONS = [
    # Agent 1: 乘→加→除→平方→减
    [
        "请只回答数字结果，不要任何解释。第1步：计算 A = 23 × 17，只输出A的值",
        "上一步结果A={A}。第2步：计算 B = A + 156，只输出B的值",
        "上一步结果B={B}。第3步：计算 C = B / 3（保留2位小数），只输出C的值",
        "上一步结果C={C}。第4步：计算 D = C 的平方（保留2位小数），只输出D的值",
        "上一步结果D={D}。第5步：计算 E = D - 1000（保留2位小数），只输出E的值",
    ],
    # Agent 2: 加→减→乘→开方→取整
    [
        "请只回答数字结果，不要任何解释。第1步：计算 X = 789 + 456，只输出X的值",
        "上一步结果X={X}。第2步：计算 Y = X - 234，只输出Y的值",
        "上一步结果Y={Y}。第3步：计算 Z = Y × 0.5（保留2位小数），只输出Z的值",
        "上一步结果Z={Z}。第4步：计算 W = Z 的平方根（保留2位小数），只输出W的值",
        "上一步结果W={W}。第5步：计算 V = W 向上取整后的值，只输出V的值",
    ],
    # Agent 3: 平方→取模→乘→减→除
    [
        "请只回答数字结果，不要任何解释。第1步：计算 P = 42 的平方，只输出P的值",
        "上一步结果P={P}。第2步：计算 Q = P 除以 100 的余数，只输出Q的值",
        "上一步结果Q={Q}。第3步：计算 R = Q × 37，只输出R的值",
        "上一步结果R={R}。第4步：计算 S = R - 500，只输出S的值",
        "上一步结果S={S}。第5步：计算 T = S 除以 7（保留2位小数），只输出T的值",
    ],
    # Agent 4: 阶乘→加→除→乘→减
    [
        "请只回答数字结果，不要任何解释。第1步：计算 F = 10 的阶乘（10!），只输出F的值",
        "上一步结果F={F}。第2步：计算 G = F + 999999，只输出G的值",
        "上一步结果G={G}。第3步：计算 H = G 除以 3628800（保留2位小数），只输出H的值",
        "上一步结果H={H}。第4步：计算 I = H × 100（保留2位小数），只输出I的值",
        "上一步结果I={I}。第5步：计算 J = I - 100（保留2位小数），只输出J的值",
    ],
    # Agent 5: 混合运算
    [
        "请只回答数字结果，不要任何解释。第1步：计算 M = 2 的 10 次方，只输出M的值",
        "上一步结果M={M}。第2步：计算 N = M + 24，只输出N的值",
        "上一步结果N={N}。第3步：计算 O = N 的立方根（保留2位小数），只输出O的值",
        "上一步结果O={O}。第4步：计算 K = O × 15（保留2位小数），只输出K的值",
        "上一步结果K={K}。第5步：计算 L = K 向下取整后的值，只输出L的值",
    ],
]

# 预期答案
EXPECTED = [
    {"A": 391, "B": 547, "C": "182.33", "D": "33244.11", "E": "32244.11"},
    {"X": 1245, "Y": 1011, "Z": "505.50", "W": "22.48", "V": 23},
    {"P": 1764, "Q": 64, "R": 2368, "S": 1868, "T": "266.86"},
    {"F": 3628800, "G": 4628799, "H": "1.28", "I": "127.56", "J": "27.56"},
    {"M": 1024, "N": 1048, "O": "10.16", "K": "152.38", "L": 152},
]


def extract_number(text: str) -> float:
    """Extract first number from text response."""
    import re
    # Try to find a number (integer or float)
    matches = re.findall(r'-?\d+\.?\d*', text.strip())
    if matches:
        return float(matches[0])
    return None


async def run_agent_session(agent_id: int, questions: list) -> dict:
    """Run a single agent through 5-step calculation."""
    results = {}
    variables = {}
    var_names = ["A", "B", "C", "D", "E", "X", "Y", "Z", "W", "V",
                 "P", "Q", "R", "S", "T", "F", "G", "H", "I", "J",
                 "M", "N", "O", "K", "L"]

    # Create session
    try:
        r = await asyncio.to_thread(
            httpx.post, f"{BASE}/session",
            json={"prompt": questions[0], "model": "glm-4-flash"},
            timeout=120
        )
        if r.status_code != 200:
            return {"agent": agent_id, "error": f"Session creation failed: {r.status_code} {r.text[:200]}"}

        data = r.json()
        session_id = data.get("session_id")
        response = data.get("response", "")
        step1_var = var_names[agent_id * 5]
        results["step_1"] = response[:100]
        variables[step1_var] = response[:50]

        # Steps 2-5
        for step in range(1, 5):
            var_idx = agent_id * 5 + step
            var_name = var_names[var_idx]
            prev_var = var_names[agent_id * 5 + step - 1]

            prompt = questions[step].replace(f"{{{prev_var}}}", variables[prev_var])

            try:
                r = await asyncio.to_thread(
                    httpx.post,
                    f"{BASE}/session/{session_id}/message",
                    json={"prompt": prompt},
                    timeout=120
                )
                if r.status_code != 200:
                    results[f"step_{step+1}"] = f"ERROR: {r.status_code}"
                    variables[var_name] = "ERROR"
                    continue

                data = r.json()
                response = data.get("response", "")
                results[f"step_{step+1}"] = response[:100]
                variables[var_name] = response[:50]

            except Exception as e:
                results[f"step_{step+1}"] = f"TIMEOUT/ERROR: {str(e)[:80]}"
                variables[var_name] = "ERROR"

        # Cleanup session
        try:
            await asyncio.to_thread(httpx.delete, f"{BASE}/session/{session_id}", timeout=10)
        except:
            pass

        return {"agent": agent_id, "results": results, "variables": variables}

    except Exception as e:
        return {"agent": agent_id, "error": str(e)[:200]}


async def main():
    print("=" * 60)
    print("A2A Multi-Agent Concurrent Test")
    print("5 agents × 5-step chained calculation")
    print("=" * 60)

    start = time.time()

    # Run 5 agents concurrently
    tasks = [
        run_agent_session(i, CALC_QUESTIONS[i])
        for i in range(5)
    ]
    results = await asyncio.gather(*tasks)

    elapsed = time.time() - start

    # Print results
    print(f"\n⏱️  Total time: {elapsed:.1f}s\n")

    for r in results:
        agent_id = r["agent"]
        print(f"{'='*40}")
        print(f"🤖 Agent {agent_id + 1}")

        if "error" in r:
            print(f"   ❌ ERROR: {r['error']}")
            continue

        for step, value in r["results"].items():
            status = "✅" if "ERROR" not in str(value) else "❌"
            print(f"   {status} {step}: {value}")

        # Show final answer
        last_step = f"step_5"
        if last_step in r["results"]:
            print(f"   📌 Final: {r['results'][last_step]}")

    print(f"\n{'='*60}")
    print("📊 Summary")
    errors = sum(1 for r in results if "error" in r)
    success = 5 - errors
    print(f"   ✅ Success: {success}/5")
    print(f"   ❌ Errors: {errors}/5")
    print(f"   ⏱️  Time: {elapsed:.1f}s")


if __name__ == "__main__":
    asyncio.run(main())
