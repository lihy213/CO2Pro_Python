# Python4Property

这个文件夹包含 `CO2_STARCCM2.jl` 的 Python 改写版本，用于调用 CoolProp 生成 CO2 在不同压力、温度下的二维物性表。

## 文件

- `CO2_property_table.py`：主程序，默认生成与 Julia 脚本一致的 CO2 物性表。

## 依赖

```powershell
pip install CoolProp
```

脚本只依赖 Python 标准库和 CoolProp，不强制依赖 pandas 或 numpy。

## 默认参数

默认网格与原 Julia 脚本保持一致：

- 温度：220-1500 K，共 1500 个点
- 压力：0.05-40 MPa，共 1000 个点
- 流体：CO2
- 输出：`CO2.csv`

这些默认值集中写在 `CO2_property_table.py` 顶部：

```python
DEFAULT_T_MAX = 1500.0
DEFAULT_P_MAX = 40.0e6
DEFAULT_T_COUNT = 1500
DEFAULT_P_COUNT = 1000
DEFAULT_WORKERS = max(1, (os.cpu_count() or 2) - 1)
```

如果在 PyCharm 中直接点击运行，不想配置命令行参数，可以直接修改这些默认变量。若同时设置了命令行参数，则命令行参数会覆盖顶部默认值。

输出字段：

| 字段 | 含义 |
|---|---|
| Pressure | 压力，Pa |
| Temperature | 温度，K |
| Density | 密度，kg/m3 |
| Viscosity | 动力黏度，Pa s |
| Entropy | 比熵，J/(kg K) |
| Enthalpy | 比焓，J/kg |
| SpecificHeatCapacity | 定压比热，J/(kg K) |
| Cv | 定容比热，J/(kg K) |
| Gamma | 比热比，Cp/Cv |
| ThermalConductivity | 导热率，W/(m K) |
| SpeedOfSound | 声速，m/s |

## 运行方式

在当前文件夹中运行：

```powershell
python CO2_property_table.py
```

指定输出文件和并行进程数：

```powershell
python CO2_property_table.py --output CO2.csv --workers 8
```

在 PyCharm 的 Run/Debug Configuration 中，也可以在 Parameters 中填写同样的参数，例如：

```powershell
--t-count 20 --p-count 20 --output CO2_test.csv --workers 4
```

减少网格点数用于测试：

```powershell
python CO2_property_table.py --t-count 20 --p-count 20 --output CO2_test.csv --workers 4
```

指定新的压力、温度范围：

```powershell
python CO2_property_table.py --t-min 300 --t-max 900 --t-count 500 --p-min 1000000 --p-max 25000000 --p-count 600 --output CO2_custom.csv
```

## 与 Julia 版本的主要区别

1. 使用 Python `ProcessPoolExecutor` 并行计算。每个任务负责一个温度行下的所有压力点，适合 CoolProp 这种计算量较重的函数调用。
2. 计算结果直接流式写入 CSV，避免一次性把 150 万个状态点全部堆在内存中。
3. 失败状态点会写入 `CO2_property_errors.log`，便于检查是否有跨相区、物性失败或输入范围问题。
4. 写入顺序按并行任务完成顺序输出。如果需要完全按温度、压力排序，可在后处理时按 `Temperature, Pressure` 排序。

## 给 STAR-CCM+ 或 Fluent 使用时的提醒

如果后续要用于真实气体物性插值表，建议先做小网格测试，确认 CO2 在目标压力温度范围内 CoolProp 没有异常点，再生成完整表格。对于 sCO2-LBE 射流模拟，还建议额外检查临界区附近的密度、声速、Cp 和 Gamma 是否平滑，因为这些量会直接影响阻塞流量、马赫数和激波位置。
