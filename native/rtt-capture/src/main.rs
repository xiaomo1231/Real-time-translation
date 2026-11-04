//! 用法：rtt-capture <进程ID> <include|exclude>
//!
//! include：只录该进程及其子进程的声音；exclude：录除该进程树以外的全部声音。
//! 输出：16000Hz 单声道 32 位浮点小端 PCM，持续写到 stdout。
//! 需要 Windows 10 build 20348 / Windows 11 以上。stdout 被关闭时退出。

use std::collections::VecDeque;
use std::io::{self, Write};
use std::process::ExitCode;
use wasapi::{initialize_mta, AudioClient, Direction, SampleType, StreamMode, WaveFormat};

const RATE: usize = 16000;
const CHUNK: usize = RATE / 20; // 50ms

fn run(pid: u32, include: bool) -> Result<(), Box<dyn std::error::Error>> {
    initialize_mta().ok()?;
    let format = WaveFormat::new(32, 32, &SampleType::Float, RATE, 1, None);
    let mut client = AudioClient::new_application_loopback_client(pid, include)?;
    let mode = StreamMode::EventsShared { autoconvert: true, buffer_duration_hns: 0 };
    client.initialize_client(&format, &Direction::Capture, &mode)?;
    let event = client.set_get_eventhandle()?;
    let capture = client.get_audiocaptureclient()?;
    client.start_stream()?;
    eprintln!("ready {RATE} 1");

    let mut out = io::stdout().lock();
    let mut queue: VecDeque<u8> = VecDeque::new();
    let chunk_bytes = CHUNK * 4;
    let mut buf = vec![0u8; chunk_bytes];
    loop {
        if event.wait_for_event(1000).is_err() {
            // 目标进程没有在播放时可能收不到事件：补一段静音，让下游正常断句
            buf.fill(0);
            out.write_all(&buf)?;
            out.flush()?;
            continue;
        }
        if capture.get_next_packet_size()?.unwrap_or(0) > 0 {
            capture.read_from_device_to_deque(&mut queue)?;
        }
        while queue.len() >= chunk_bytes {
            for b in buf.iter_mut() {
                *b = queue.pop_front().unwrap_or(0);
            }
            out.write_all(&buf)?;
        }
        out.flush()?;
    }
}

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().collect();
    if args.len() != 3 {
        eprintln!("用法：rtt-capture <进程ID> <include|exclude>");
        return ExitCode::from(2);
    }
    let Ok(pid) = args[1].parse::<u32>() else {
        eprintln!("进程ID 无效：{}", args[1]);
        return ExitCode::from(2);
    };
    let include = match args[2].as_str() {
        "include" => true,
        "exclude" => false,
        other => {
            eprintln!("模式只能是 include 或 exclude：{other}");
            return ExitCode::from(2);
        }
    };
    match run(pid, include) {
        Ok(()) => ExitCode::SUCCESS,
        Err(e) => {
            // stdout 被关闭属于正常退出
            if let Some(ioe) = e.downcast_ref::<io::Error>() {
                if ioe.kind() == io::ErrorKind::BrokenPipe {
                    return ExitCode::SUCCESS;
                }
            }
            eprintln!("error {e}");
            ExitCode::from(1)
        }
    }
}
