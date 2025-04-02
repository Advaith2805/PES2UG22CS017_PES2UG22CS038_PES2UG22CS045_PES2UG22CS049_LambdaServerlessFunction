function handler(event) {
    return { message: "Hello, world!", event };
}

console.log(JSON.stringify(handler(process.argv[2] ? JSON.parse(process.argv[2]) : {})));